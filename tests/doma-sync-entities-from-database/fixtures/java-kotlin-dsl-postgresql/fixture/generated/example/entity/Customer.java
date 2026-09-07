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
    @Id
    @Column(name = "customer_id")
    Long customerId;

    /** Email address */
    @Column(name = "email")
    String email;

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

    /** Returns the email. */
    public String getEmail() {
        return email;
    }

    /** Sets the email. */
    public void setEmail(String email) {
        this.email = email;
    }
}
