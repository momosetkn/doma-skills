package example.entity;

import org.seasar.doma.Column;
import org.seasar.doma.Entity;
import org.seasar.doma.Id;
import org.seasar.doma.Metamodel;
import org.seasar.doma.Table;

/** Customers */
@Entity(metamodel = @Metamodel)
@Table(schema = "public", name = "customer")
public class Customer {

    /** Tenant ID */
    @Id
    @Column(name = "tenant_id")
    Long tenantId;

    /** Customer ID */
    @Column(name = "customer_id")
    Long customerId;

    /** Returns the tenantId. */
    public Long getTenantId() {
        return tenantId;
    }

    /** Sets the tenantId. */
    public void setTenantId(Long tenantId) {
        this.tenantId = tenantId;
    }

    /** Returns the customerId. */
    public Long getCustomerId() {
        return customerId;
    }

    /** Sets the customerId. */
    public void setCustomerId(Long customerId) {
        this.customerId = customerId;
    }

// HANDWRITTEN-BEGIN:customer-key
    /** Application-owned customer key. */
    public String customerKey() {
        return tenantId + ":" + customerId;
    }
// HANDWRITTEN-END:customer-key
}
