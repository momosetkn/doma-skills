package example.entity;

import org.seasar.doma.Column;
import org.seasar.doma.Entity;
import org.seasar.doma.Id;
import org.seasar.doma.Table;

/** Customers */
@Entity
@Table(catalog = "fixture_catalog", name = "customer")
public class Customer {

    /** Customer ID */
    @Id
    @Column(name = "customer_id")
    Long customerId;

    /** Returns the customerId. */
    public Long getCustomerId() {
        return customerId;
    }

    /** Sets the customerId. */
    public void setCustomerId(Long customerId) {
        this.customerId = customerId;
    }
}
